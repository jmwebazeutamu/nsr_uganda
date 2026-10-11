from django.apps import AppConfig


class GrievanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.grievance"
    label = "grievance"
    verbose_name = "Grievance (GRM)"

    def ready(self) -> None:
        # Wire the UPD-commit -> GRM-close signal handler.
        from . import signals  # noqa: F401

        # Describe the STAAC exchange to the integrations screen. The
        # adapter registers itself here so DIH never has to import
        # GRM to learn what a partner credential looks like — the
        # same reason the connector registry is populated on app
        # load.
        from .external import integration  # noqa: F401
