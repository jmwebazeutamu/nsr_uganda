from django.apps import AppConfig


class GrievanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.grievance"
    label = "grievance"
    verbose_name = "Grievance (GRM)"

    def ready(self) -> None:
        # Wire the UPD-commit -> GRM-close signal handler.
        from . import signals  # noqa: F401
