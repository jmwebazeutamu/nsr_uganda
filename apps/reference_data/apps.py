from django.apps import AppConfig


class ReferenceDataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reference_data"
    label = "reference_data"
    verbose_name = "Reference Data (REF-DATA)"

    def ready(self) -> None:
        # Wire post_save / post_delete signals on ChoiceList /
        # ChoiceOption so the resolver's lru_cache flushes whenever
        # the admin (or a migration) edits the closed lists.
        from . import signals  # noqa: F401
