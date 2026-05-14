from django.apps import AppConfig


class ReferenceDataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reference_data"
    label = "reference_data"
    verbose_name = "Reference Data (REF-DATA)"
