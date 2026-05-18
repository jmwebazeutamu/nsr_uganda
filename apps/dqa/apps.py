from django.apps import AppConfig


class DqaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dqa"
    label = "dqa"
    verbose_name = "Data Quality (DAT-DQA)"

    def ready(self) -> None:
        # US-080 — re-evaluate rules on UPD commits.
        from . import signals  # noqa: F401
