from django.apps import AppConfig


class IngestionHubConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ingestion_hub"
    label = "ingestion_hub"
    verbose_name = "Ingestion Hub / DIH (ING)"
