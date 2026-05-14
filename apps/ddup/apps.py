from django.apps import AppConfig


class DdupConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ddup"
    label = "ddup"
    verbose_name = "Deduplication (DAT-DDUP)"
