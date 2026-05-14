from django.apps import AppConfig


class PmtConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pmt"
    label = "pmt"
    verbose_name = "Proxy Means Test (PMT)"

    def ready(self) -> None:
        # Wire the UPD post-commit recompute hook.
        from . import signals  # noqa: F401
